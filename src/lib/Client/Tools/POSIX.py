'''All POSIX Type client support for Bcfg2'''
__revision__ = '$Revision$'

from stat import S_ISVTX, S_ISGID, S_ISUID, S_IXUSR, S_IWUSR, S_IRUSR, S_IXGRP
from stat import S_IWGRP, S_IRGRP, S_IXOTH, S_IWOTH, S_IROTH, ST_MODE, S_ISDIR
from stat import S_IFREG, ST_UID, ST_GID, S_ISREG, S_IFDIR, S_ISLNK

import binascii, difflib, grp, os, pwd, xml.sax.saxutils
import Bcfg2.Client.Tools

def calcPerms(initial, perms):
    '''This compares ondisk permissions with specified ones'''
    pdisp = [{1:S_ISVTX, 2:S_ISGID, 4:S_ISUID}, {1:S_IXUSR, 2:S_IWUSR, 4:S_IRUSR},
             {1:S_IXGRP, 2:S_IWGRP, 4:S_IRGRP}, {1:S_IXOTH, 2:S_IWOTH, 4:S_IROTH}]
    tempperms = initial
    if len(perms) == 3:
        perms = '0%s' % (perms)
    pdigits = [int(perms[digit]) for digit in range(4)]
    for index in range(4):
        for (num, perm) in pdisp[index].iteritems():
            if pdigits[index] & num:
                tempperms |= perm
    return tempperms

class POSIX(Bcfg2.Client.Tools.Tool):
    '''POSIX File support code'''
    __name__ = 'POSIX'
    __handles__ = [('ConfigFile', None), ('Directory', None), ('Permissions', None), \
                   ('SymLink', None)]
    __req__ = {'ConfigFile': ['name', 'owner', 'group', 'perms'],
               'Directory': ['name', 'owner', 'group', 'perms'],
               'Permissions': ['name', 'owner', 'group', 'perms'],
               'SymLink': ['name', 'to']}

    def VerifySymLink(self, entry, _):
        '''Verify SymLink Entry'''
        try:
            sloc = os.readlink(entry.get('name'))
            if sloc == entry.get('to'):
                return True
            self.logger.debug("Symlink %s points to %s, should be %s" % \
                              (entry.get('name'), sloc, entry.get('to')))
            entry.set('current_to', sloc)
            return False
        except OSError:
            entry.set('current_exists', 'false')
            return False

    def InstallSymLink(self, entry):
        '''Install SymLink Entry'''
        self.logger.info("Installing Symlink %s" % (entry.get('name')))
        try:
            fmode = os.lstat(entry.get('name'))[ST_MODE]
            if S_ISREG(fmode) or S_ISLNK(fmode):
                self.logger.debug("Non-directory entry already exists at %s" % \
                                  (entry.get('name')))
                os.unlink(entry.get('name'))
            elif S_ISDIR(fmode):
                self.logger.debug("Directory entry already exists at %s" % (entry.get('name')))
                self.cmd.run("mv %s/ %s.bak" % (entry.get('name'), entry.get('name')))
            else:
                os.unlink(entry.get('name'))
        except OSError:
            self.logger.info("Symlink %s cleanup failed" % (entry.get('name')))
        try:
            os.symlink(entry.get('to'), entry.get('name'))
            return True
        except OSError:
            return False

    def VerifyDirectory(self, entry, _):
        '''Verify Directory Entry'''
        while len(entry.get('perms', '')) < 4:
            entry.set('perms', '0' + entry.get('perms', ''))
        try:
            ondisk = os.stat(entry.get('name'))
        except OSError:
            entry.set('current_exists', 'false')
            self.logger.debug("%s %s does not exist" %
                              (entry.tag, entry.get('name')))
            return False
        try:
            owner = pwd.getpwuid(ondisk[ST_UID])[0]
            group = grp.getgrgid(ondisk[ST_GID])[0]
        except (OSError, KeyError):
            self.logger.error('User resolution failing')
            owner = 'root'
            group = 'root'
        perms = oct(os.stat(entry.get('name'))[ST_MODE])[-4:]
        if ((owner == entry.get('owner')) and
            (group == entry.get('group')) and
            (perms == entry.get('perms'))):
            return True
        else:
            if owner != entry.get('owner'):
                entry.set('current_owner', owner)
                self.logger.debug("%s %s ownership wrong" % (entry.tag, entry.get('name')))
            if group != entry.get('group'):
                entry.set('current_group', group)
                self.logger.debug("%s %s group wrong" % (entry.tag, entry.get('name')))
            if perms != entry.get('perms'):
                entry.set('current_perms', perms)
                self.logger.debug("%s %s permissions wrong: are %s should be %s" %
                               (entry.tag, entry.get('name'), perms, entry.get('perms')))
            return False

    def InstallDirectory(self, entry):
        '''Install Directory Entry'''
        self.logger.info("Installing Directory %s" % (entry.get('name')))
        try:
            fmode = os.lstat(entry.get('name'))
            if not S_ISDIR(fmode[ST_MODE]):
                self.logger.debug("Found a non-directory entry at %s" % (entry.get('name')))
                try:
                    os.unlink(entry.get('name'))
                except OSError:
                    self.logger.info("Failed to unlink %s" % (entry.get('name')))
                    return False
            else:
                self.logger.debug("Found a pre-existing directory at %s" % (entry.get('name')))
                exists = True
        except OSError:
            # stat failed
            exists = False

        if not exists:
            parent = "/".join(entry.get('name').split('/')[:-1])
            if parent:
                try:
                    os.lstat(parent)
                except:
                    self.logger.debug('Creating parent path for directory %s' % (entry.get('name')))
                    for idx in xrange(len(parent.split('/')[:-1])):
                        current = '/'+'/'.join(parent.split('/')[1:2+idx])
                        try:
                            sloc = os.lstat(current)
                            try:
                                if not S_ISDIR(sloc[ST_MODE]):
                                    os.unlink(current)
                                    os.mkdir(current)
                            except OSError:
                                return False
                        except OSError:
                            try:
                                os.mkdir(current)
                            except OSError:
                                return False

            try:
                os.mkdir(entry.get('name'))
            except OSError:
                self.logger.error('Failed to create directory %s' % (entry.get('name')))
                return False
        try:
            os.chown(entry.get('name'),
                  pwd.getpwnam(entry.get('owner'))[2], grp.getgrnam(entry.get('group'))[2])
            os.chmod(entry.get('name'), calcPerms(S_IFDIR, entry.get('perms')))
            return True
        except (OSError, KeyError):
            self.logger.error('Permission fixup failed for %s' % (entry.get('name')))
            return False

    def VerifyConfigFile(self, entry, _):
        '''Install ConfigFile Entry'''
        # configfile verify is permissions check + content check
        permissionStatus = self.VerifyDirectory(entry, _)
        if entry.get('encoding', 'ascii') == 'base64':
            tempdata = binascii.a2b_base64(entry.text)
        elif entry.get('empty', 'false') == 'true':
            tempdata = ''
        else:
            if entry.text == None:
                self.logger.error("Cannot verify incomplete ConfigFile %s" % (entry.get('name')))
                return False
            tempdata = entry.text

        try:
            content = open(entry.get('name')).read()
        except IOError:
            # file does not exist
            return False
        contentStatus = content == tempdata
        if not contentStatus:
            diff = '\n'.join([x for x in difflib.unified_diff(content.split('\n'), tempdata.split('\n'))])
            try:
                entry.set("current_diff", xml.sax.saxutils.quoteattr(diff))
            except:
                pass
        return contentStatus and permissionStatus

    def InstallConfigFile(self, entry):
        '''Install ConfigFile Entry'''
        if entry.text == None and entry.get('empty', 'false') != 'true':
            self.logger.info("Incomplete information for ConfigFile %s" % entry.get('name'))
            return False
        self.logger.info("Installing ConfigFile %s" % (entry.get('name')))

        parent = "/".join(entry.get('name').split('/')[:-1])
        if parent:
            try:
                os.lstat(parent)
            except:
                self.logger.debug('Creating parent path for config file %s' % (entry.get('name')))
                for idx in xrange(len(parent.split('/')[:-1])):
                    current = '/'+'/'.join(parent.split('/')[1:2+idx])
                    try:
                        sloc = os.lstat(current)
                        try:
                            if not S_ISDIR(sloc[ST_MODE]):
                                os.unlink(current)
                                os.mkdir(current)
                        except OSError:
                            return False
                    except OSError:
                        try:
                            os.mkdir(current)
                        except OSError:
                            return False

        # If we get here, then the parent directory should exist
        try:
            newfile = open("%s.new"%(entry.get('name')), 'w')
            if entry.get('encoding', 'ascii') == 'base64':
                filedata = binascii.a2b_base64(entry.text)
            elif entry.get('empty', 'false') == 'true':
                filedata = ''
            else:
                filedata = entry.text
            newfile.write(filedata)
            newfile.close()
            try:
                os.chown(newfile.name, pwd.getpwnam(entry.get('owner'))[2],
                         grp.getgrnam(entry.get('group'))[2])
            except KeyError:
                os.chown(newfile.name, 0, 0)
            os.chmod(newfile.name, calcPerms(S_IFREG, entry.get('perms')))
            if entry.get("paranoid", False) and self.setup.get("paranoid", False):
                self.cmd.run("cp %s /var/cache/bcfg2/%s" % (entry.get('name')))
            os.rename(newfile.name, entry.get('name'))
            return True
        except (OSError, IOError), err:
            if err.errno == 13:
                self.logger.info("Failed to open %s for writing" % (entry.get('name')))
            else:
                print err
            return False
