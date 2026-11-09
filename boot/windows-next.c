#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <unistd.h>

#define GLOBAL "8be4df61-93ca-11d2-aa0d-00e098032b8c"
#ifndef ESP_GUID
#error "Pass the target ESP PARTUUID as ESP_GUID"
#endif
static const char *vars = "/sys/firmware/efi/efivars";
static const char *windows = "\\EFI\\Microsoft\\Boot\\bootmgfw.efi";
static unsigned u16(const unsigned char *p) { return p[0] | (p[1] << 8); }
static unsigned u32(const unsigned char *p) { return u16(p) | (u16(p+2) << 16); }
static size_t readvar(const char *name, unsigned char *buf, size_t cap) {
    char path[1024]; snprintf(path, sizeof path, "%s/%s-" GLOBAL, vars, name);
    int fd = open(path, O_RDONLY | O_NOFOLLOW);
    if (fd < 0) return 0;
    ssize_t n = read(fd, buf, cap); close(fd);
    return n > 0 ? (size_t)n : 0;
}
static int writevar(const char *name, const unsigned char *buf, size_t n) {
    char path[1024]; snprintf(path, sizeof path, "%s/%s-" GLOBAL, vars, name);
    int fd = open(path, O_WRONLY | O_CREAT | O_NOFOLLOW, 0600);
    if (fd < 0) { perror("Open firmware variable"); return -1; }
    ssize_t written = write(fd, buf, n); int saved = errno; close(fd); errno = saved;
    if (written != (ssize_t)n) { perror("Write firmware variable"); return -1; }
    unsigned char check[65536];
    if (readvar(name, check, sizeof check) != n || memcmp(buf, check, n)) {
        fputs("Firmware variable readback differs\n", stderr); return -1;
    }
    return 0;
}
static int guid_bytes(const char *s, unsigned char *out) {
    unsigned a,b,c,d[8];
    if (sscanf(s, "%8x-%4x-%4x-%2x%2x-%2x%2x%2x%2x%2x%2x", &a,&b,&c,
               &d[0],&d[1],&d[2],&d[3],&d[4],&d[5],&d[6],&d[7]) != 11) return -1;
    for (int i=0;i<4;i++) out[i]=a>>(8*i);
    out[4]=b;out[5]=b>>8;out[6]=c;out[7]=c>>8;
    for(int i=0;i<8;i++) out[8+i]=d[i];
    return 0;
}
/* Parse EFI_LOAD_OPTION and its device path; require the exact GPT ESP and
 * complete Windows loader path, not a label or a substring in optional data. */
static int matches(const unsigned char *p, size_t n, const unsigned char *guid) {
    if(n<12 || !(u32(p+4)&1)) return 0;
    size_t start=10, len=u16(p+8);
    while(start+1<n && u16(p+start)) start+=2;
    start+=2;
    if(start>n || len>n-start) return 0;
    size_t end=start+len; int disk=0, file=0, ended=0;
    for(size_t pos=start;pos+4<=end;) {
        unsigned type=p[pos],sub=p[pos+1],size=u16(p+pos+2);
        if(size<4 || size>end-pos) return 0;
        if(type==4 && sub==1) {
            if(disk || size!=42 || p[pos+40]!=2 || p[pos+41]!=2 ||
               memcmp(p+pos+24,guid,16)) return 0;
            disk=1;
        } else if(type==4 && sub==4) {
            size_t chars=strlen(windows);
            if(file || size!=4+2*(chars+1)) return 0;
            for(size_t j=0;j<chars;j++)
                if(p[pos+4+2*j+1] || tolower(p[pos+4+2*j])!=tolower((unsigned char)windows[j])) return 0;
            if(u16(p+pos+4+2*chars)) return 0;
            file=1;
        } else if(type==127) {
            if(sub!=255 || size!=4 || pos+size!=end) return 0;
            ended=1;
        }
        pos+=size;
    }
    return disk && file && ended;
}



int main(int argc, char **argv) {
    int init=getpid()==1, set=init;
    setvbuf(stdout,NULL,_IONBF,0);
    if(!init) {
        if(argc<2 || (strcmp(argv[1],"--check") && strcmp(argv[1],"--set"))) {
            fputs("Usage: windows-next --check|--set [test-variable-directory]\n",stderr);return 2;
        }
        set=!strcmp(argv[1],"--set");
        if(argc==3) vars=argv[2];
    } else {
        mkdir("/proc",0555);mkdir("/sys",0555);mkdir("/dev",0755);
        if(mount("proc","/proc","proc",0,NULL) || mount("sysfs","/sys","sysfs",0,NULL) ||
           mount("devtmpfs","/dev","devtmpfs",0,NULL) ||
           mount("efivarfs",vars,"efivarfs",0,NULL)) goto fail;
        int fd=open("/dev/console",O_RDWR);
        if(fd>=0){dup2(fd,0);dup2(fd,1);dup2(fd,2);if(fd>2)close(fd);}
    }
    unsigned char guid[16],buf[65536]; guid_bytes(ESP_GUID,guid);
    DIR *dir=opendir(vars); if(!dir) {perror("Read firmware entries");goto fail;}
    struct dirent *e; unsigned found=0,id=0;
    while((e=readdir(dir))) {
        if(strlen(e->d_name)!=45 || strncmp(e->d_name,"Boot",4) || strcmp(e->d_name+8,"-" GLOBAL))continue;
        int valid=1;for(int j=4;j<8;j++)if(!isxdigit((unsigned char)e->d_name[j]))valid=0;
        if(!valid)continue;
        char name[9];memcpy(name,e->d_name,8);name[8]=0;
        size_t n=readvar(name,buf,sizeof buf);
        if(matches(buf,n,guid)){found++;id=strtoul(name+4,NULL,16);}
    }
    closedir(dir);
    if(found!=1){fprintf(stderr,"Expected one direct Windows loader on the installed ESP; found %u\n",found);goto fail;}
    printf("Verified direct Windows firmware entry: Boot%04X\n",id);
    if(set) {
        unsigned char next[]={7,0,0,0,id&255,id>>8};
        size_t old=readvar("BootNext",buf,sizeof buf);
        if(old && (old!=6 || memcmp(buf,next,6))) {
            fputs("An unrelated one-time boot is already scheduled\n",stderr);goto fail;
        }
        if(writevar("BootNext",next,sizeof next))goto fail;
        puts("WINDOWS_NEXT_READY");
    }
    if(init) {sync();reboot(RB_AUTOBOOT);goto fail;}
    return 0;
fail:
    perror("Windows handoff stopped");
    if(init) {
        puts("No Windows boot was attempted. Use your firmware boot menu and select Windows Boot Manager. Press Enter to power off.");
        getchar();reboot(RB_POWER_OFF);for(;;)pause();
    }
    return 1;
}
