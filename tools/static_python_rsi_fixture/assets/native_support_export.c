/* Source-owned, fixed Zig seed link and same-command cache export.
 * This is an observation helper, not immutable custody or input authority.
 * It never executes the generated seed and never selects a support candidate.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define MAX_ENTRIES 32768U
#define MAX_CACHE_BYTES (UINT64_C(512) * 1024 * 1024)
#define MAX_FILE_BYTES (UINT64_C(128) * 1024 * 1024)
#define MAX_BUNDLE_BYTES (UINT64_C(128) * 1024 * 1024)
#define MAX_SEED_BYTES (UINT64_C(16) * 1024 * 1024)
#define MAX_PATH_BYTES 480U
#define ABS_PATH_BYTES 4095U
#define DIR_FLAGS (O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
#define READ_FLAGS (O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
#if defined(__APPLE__)
#define STAT_MTIME st_mtimespec
#define STAT_CTIME st_ctimespec
#else
#define STAT_MTIME st_mtim
#define STAT_CTIME st_ctim
#endif

struct hash { uint32_t h[8]; uint64_t bytes; unsigned used; unsigned char block[64]; };
static const uint32_t hash_k[64] = {
    0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
    0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
    0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
    0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
    0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
    0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
    0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
    0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U
};
static uint32_t rotate(uint32_t v, unsigned n) { return (v >> n) | (v << (32U - n)); }
static uint32_t read32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static void hash_block(struct hash *s) {
    uint32_t w[64], a=s->h[0], b=s->h[1], c=s->h[2], d=s->h[3];
    uint32_t e=s->h[4], f=s->h[5], g=s->h[6], h=s->h[7];
    for (unsigned i=0;i<16;i++) w[i]=read32(s->block+4*i);
    for (unsigned i=16;i<64;i++) {
        uint32_t x=w[i-15], y=w[i-2];
        w[i]=w[i-16]+(rotate(x,7)^rotate(x,18)^(x>>3))+w[i-7]+(rotate(y,17)^rotate(y,19)^(y>>10));
    }
    for (unsigned i=0;i<64;i++) {
        uint32_t t1=h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^((~e)&g))+hash_k[i]+w[i];
        uint32_t t2=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c));
        h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    s->h[0]+=a;s->h[1]+=b;s->h[2]+=c;s->h[3]+=d;
    s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;
}
static void hash_init(struct hash *s) {
    const uint32_t initial[8]={0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,
                               0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U};
    memcpy(s->h,initial,sizeof initial);s->bytes=0;s->used=0;
}
static void hash_update(struct hash *s, const void *data, size_t size) {
    const unsigned char *p=data;s->bytes+=size;
    while(size) {
        size_t n=64U-s->used;if(n>size)n=size;
        memcpy(s->block+s->used,p,n);s->used+=(unsigned)n;p+=n;size-=n;
        if(s->used==64){hash_block(s);s->used=0;}
    }
}
static void hash_finish(struct hash *s, unsigned char out[32]) {
    uint64_t bits=s->bytes*8U;
    s->block[s->used++]=0x80;
    if(s->used>56){memset(s->block+s->used,0,64-s->used);hash_block(s);s->used=0;}
    memset(s->block+s->used,0,56-s->used);
    for(unsigned i=0;i<8;i++)s->block[63-i]=(unsigned char)(bits>>(8*i));
    hash_block(s);
    for(unsigned i=0;i<8;i++)for(unsigned j=0;j<4;j++)out[4*i+j]=(unsigned char)(s->h[i]>>(24-8*j));
}

struct row {
    char path[MAX_PATH_BYTES+1];
    unsigned cache, kind;
    struct stat info;
    unsigned char digest[32];
};
struct inventory { struct row *rows; unsigned count; uint64_t bytes; };
struct output { int fd; uint64_t bytes; struct hash digest; };

static void refuse(const char *reason, int code) {
    fprintf(stderr,"native_support_export_%s\n",reason);exit(code);
}
static int same_stat(const struct stat *a,const struct stat *b) {
    return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_mode==b->st_mode &&
           a->st_nlink==b->st_nlink && a->st_size==b->st_size &&
           a->STAT_MTIME.tv_sec==b->STAT_MTIME.tv_sec && a->STAT_MTIME.tv_nsec==b->STAT_MTIME.tv_nsec &&
           a->STAT_CTIME.tv_sec==b->STAT_CTIME.tv_sec && a->STAT_CTIME.tv_nsec==b->STAT_CTIME.tv_nsec;
}
static int valid_component(const char *s,size_t n) {
    if(!n || (n==1 && s[0]=='.') || (n==2 && s[0]=='.' && s[1]=='.'))return 0;
    for(size_t i=0;i<n;i++)if((unsigned char)s[i]<=32 || (unsigned char)s[i]>126 || s[i]=='\\' || s[i]==':' || s[i]=='/')return 0;
    return 1;
}
static void absolute_path(const char *path) {
    size_t length=strlen(path);
    if(length<2 || length>ABS_PATH_BYTES || path[0]!='/')refuse("argument_path",64);
    const char *part=path+1;
    for(const char *p=part;;p++)if(*p=='/' || !*p){
        if(!valid_component(part,(size_t)(p-part)))refuse("argument_path",64);
        if(!*p)break;
        part=p+1;
    }
}
static int overlap(const char *a,const char *b) {
    size_t n=strlen(a);return !strncmp(a,b,n) && (b[n]==0 || b[n]=='/');
}
static int parent_fd(const char *path,char leaf[ABS_PATH_BYTES+1]) {
    char copy[ABS_PATH_BYTES+1];strcpy(copy,path);
    char *last=strrchr(copy,'/');strcpy(leaf,last+1);*last=0;
    int fd=open("/",DIR_FLAGS);if(fd<0)refuse("parent_open",65);
    if(last==copy)return fd;
    char *part=copy+1;
    while(*part){
        char *end=strchr(part,'/');if(end)*end=0;
        int next=openat(fd,part,DIR_FLAGS);if(next<0)refuse("parent_open",65);
        close(fd);fd=next;if(!end)break;part=end+1;
    }
    return fd;
}
static int open_absolute(const char *path,int flags) {
    char leaf[ABS_PATH_BYTES+1];int parent=parent_fd(path,leaf);
    int fd=openat(parent,leaf,flags);close(parent);return fd;
}
static int reserve_output(const char *path) {
    char leaf[ABS_PATH_BYTES+1];int parent=parent_fd(path,leaf);
    int fd=openat(parent,leaf,O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(fd<0)refuse("output_not_fresh",65);
    if(fsync(parent))refuse("output_parent_fsync",65);
    close(parent);return fd;
}
static int create_cache(const char *path) {
    char leaf[ABS_PATH_BYTES+1];int parent=parent_fd(path,leaf);
    if(mkdirat(parent,leaf,0700))refuse("cache_not_fresh",65);
    int fd=openat(parent,leaf,DIR_FLAGS);
    if(fd<0 || fchmod(fd,0700) || fsync(parent))refuse("cache_create",65);
    close(parent);return fd;
}
static int candidate(const char *path) {
    const char *name=strrchr(path,'/');name=name?name+1:path;
    const char *names[]={"crt1.o","crti.o","crtn.o","libc.a","libzigc.a","libubsan_rt.a","libcompiler_rt.a"};
    for(unsigned i=0;i<sizeof names/sizeof names[0];i++)if(!strcmp(name,names[i]))return 1;
    return 0;
}
static void output_bytes(struct output *out,const void *raw,size_t size) {
    if(size>MAX_BUNDLE_BYTES-out->bytes)refuse("bundle_bounds",68);
    const unsigned char *p=raw;size_t remaining=size;
    while(remaining){
        ssize_t n=write(out->fd,p,remaining);
        if(n<0 && errno==EINTR)continue;
        if(n<=0)refuse("bundle_write",68);
        p+=n;remaining-=(size_t)n;
    }
    hash_update(&out->digest,raw,size);out->bytes+=size;
}
static void output_integer(struct output *out,uint64_t value,unsigned width) {
    unsigned char raw[8];
    for(unsigned i=0;i<width;i++)raw[width-1-i]=(unsigned char)(value>>(8*i));
    output_bytes(out,raw,width);
}
static void file_digest(int directory,const char *name,const struct stat *expected,
                        unsigned char digest[32],struct output *out) {
    int fd=openat(directory,name,READ_FLAGS);struct stat before,after,named;
    if(fd<0 || fstat(fd,&before) || !S_ISREG(before.st_mode) || !same_stat(expected,&before) ||
       before.st_size<0 || (uint64_t)before.st_size>MAX_FILE_BYTES)refuse("cache_file",67);
    struct hash hash;hash_init(&hash);uint64_t count=0;unsigned char block[65536];
    for(;;){
        ssize_t n=read(fd,block,sizeof block);
        if(n<0 && errno==EINTR)continue;
        if(n<0)refuse("cache_read",67);
        if(!n)break;
        count+=(uint64_t)n;if(count>MAX_FILE_BYTES || count>(uint64_t)before.st_size)refuse("cache_bounds",67);
        hash_update(&hash,block,(size_t)n);if(out)output_bytes(out,block,(size_t)n);
    }
    if(fstat(fd,&after) || fstatat(directory,name,&named,AT_SYMLINK_NOFOLLOW) ||
       count!=(uint64_t)before.st_size || !same_stat(&before,&after) || !same_stat(&before,&named))refuse("cache_drift",67);
    close(fd);hash_finish(&hash,digest);
}
static void scan_directory(int fd,const char *prefix,unsigned cache,struct inventory *inventory) {
    struct stat before,after;if(fstat(fd,&before))refuse("cache_directory",67);
    int scan=openat(fd,".",DIR_FLAGS);if(scan<0)refuse("cache_directory",67);
    DIR *directory=fdopendir(scan);if(!directory)refuse("cache_directory",67);
    for(;;){
        errno=0;struct dirent *entry=readdir(directory);
        if(!entry){if(errno)refuse("cache_directory",67);break;}
        if(!strcmp(entry->d_name,".") || !strcmp(entry->d_name,".."))continue;
        size_t n=strlen(entry->d_name),base=strlen(prefix);
        if(!valid_component(entry->d_name,n) || base+(base?1:0)+n>MAX_PATH_BYTES)refuse("cache_path",67);
        if(inventory->count==MAX_ENTRIES)refuse("cache_bounds",67);
        struct row *row=&inventory->rows[inventory->count++];
        if(base){memcpy(row->path,prefix,base);row->path[base++]='/';}
        memcpy(row->path+base,entry->d_name,n+1);row->cache=cache;
        if(fstatat(fd,entry->d_name,&row->info,AT_SYMLINK_NOFOLLOW))refuse("cache_entry",67);
        if(S_ISDIR(row->info.st_mode)){
            row->kind=1;
            int child=openat(fd,entry->d_name,DIR_FLAGS);struct stat opened,named;
            if(child<0 || fstat(child,&opened) || !same_stat(&row->info,&opened))refuse("cache_drift",67);
            scan_directory(child,row->path,cache,inventory);
            if(fstat(child,&opened) || fstatat(fd,entry->d_name,&named,AT_SYMLINK_NOFOLLOW) ||
               !same_stat(&row->info,&opened) || !same_stat(&row->info,&named))refuse("cache_drift",67);
            close(child);
        }else if(S_ISREG(row->info.st_mode)){
            row->kind=2;
            if(row->info.st_size<0 || (uint64_t)row->info.st_size>MAX_FILE_BYTES ||
               (uint64_t)row->info.st_size>MAX_CACHE_BYTES-inventory->bytes)refuse("cache_bounds",67);
            inventory->bytes+=(uint64_t)row->info.st_size;
            file_digest(fd,entry->d_name,&row->info,row->digest,NULL);
            if(candidate(row->path) && (!row->info.st_size || (row->info.st_mode&0111)))refuse("candidate_mode",67);
        }else refuse("cache_entry",67);
    }
    closedir(directory);
    if(fstat(fd,&after) || !same_stat(&before,&after))refuse("cache_drift",67);
}
static int row_order(const void *left,const void *right) {
    const struct row *a=left,*b=right;
    if(a->cache!=b->cache)return a->cache<b->cache?-1:1;
    return strcmp(a->path,b->path);
}
static struct inventory scan_caches(int roots[2],const char *paths[2],struct stat originals[2]) {
    struct inventory result={calloc(MAX_ENTRIES,sizeof(struct row)),0,0};
    if(!result.rows)refuse("memory",67);
    for(unsigned cache=0;cache<2;cache++){
        int named=open_absolute(paths[cache],DIR_FLAGS);struct stat current;
        if(named<0 || fstat(named,&current) || !same_stat(&originals[cache],&current))refuse("cache_root_drift",67);
        close(named);scan_directory(roots[cache],"",cache,&result);
        if(fstat(roots[cache],&current) || !same_stat(&originals[cache],&current))refuse("cache_root_drift",67);
    }
    qsort(result.rows,result.count,sizeof(struct row),row_order);
    for(unsigned i=1;i<result.count;i++)if(!row_order(&result.rows[i-1],&result.rows[i]))refuse("cache_duplicate",67);
    return result;
}
static void compare_inventories(const struct inventory *a,const struct inventory *b) {
    if(a->count!=b->count || a->bytes!=b->bytes)refuse("cache_drift",67);
    for(unsigned i=0;i<a->count;i++){
        const struct row *left=&a->rows[i],*right=&b->rows[i];
        if(row_order(left,right) || left->kind!=right->kind || !same_stat(&left->info,&right->info) ||
           memcmp(left->digest,right->digest,32))refuse("cache_drift",67);
    }
}
static int relative_parent(int root,const char *path,char leaf[MAX_PATH_BYTES+1]) {
    char copy[MAX_PATH_BYTES+1];strcpy(copy,path);char *last=strrchr(copy,'/');
    if(!last){strcpy(leaf,copy);return dup(root);}
    strcpy(leaf,last+1);*last=0;int fd=dup(root);if(fd<0)refuse("cache_directory",67);
    char *part=copy;
    while(*part){
        char *end=strchr(part,'/');if(end)*end=0;
        int child=openat(fd,part,DIR_FLAGS);if(child<0)refuse("cache_directory",67);
        close(fd);fd=child;if(!end)break;part=end+1;
    }
    return fd;
}
static void export_inventory(struct output *out,const struct inventory *inventory,int roots[2],struct stat root_info[2]) {
    unsigned candidates=0;
    for(unsigned i=0;i<inventory->count;i++)if(inventory->rows[i].kind==2 && candidate(inventory->rows[i].path))candidates++;
    output_bytes(out,"LZSUP01\n",8);output_integer(out,inventory->count,4);output_integer(out,candidates,4);
    for(unsigned cache=0;cache<2;cache++){
        output_integer(out,1,1);output_integer(out,(uint32_t)root_info[cache].st_mode,4);
    }
    for(unsigned i=0;i<inventory->count;i++){
        const struct row *row=&inventory->rows[i];size_t size=strlen(row->path);
        output_integer(out,row->cache,1);output_integer(out,row->kind,1);output_integer(out,size,2);
        output_integer(out,(uint32_t)row->info.st_mode,4);
        output_integer(out,row->kind==2?(uint64_t)row->info.st_size:0,8);
        output_bytes(out,row->digest,32);output_bytes(out,row->path,size);
        if(row->kind==2 && candidate(row->path)){
            char leaf[MAX_PATH_BYTES+1];unsigned char digest[32];
            int parent=relative_parent(roots[row->cache],row->path,leaf);
            if(parent<0)refuse("cache_directory",67);
            file_digest(parent,leaf,&row->info,digest,out);close(parent);
            if(memcmp(digest,row->digest,32))refuse("cache_drift",67);
        }
    }
}
static void verify_bundle(struct output *out,const char *path) {
    unsigned char expected[32],observed[32],block[65536];struct hash hash;
    if(fsync(out->fd) || fchmod(out->fd,0400) || fsync(out->fd) || lseek(out->fd,0,SEEK_SET)<0)refuse("bundle_fsync",68);
    struct stat before,after,named;if(fstat(out->fd,&before))refuse("bundle_readback",68);
    hash_finish(&out->digest,expected);hash_init(&hash);uint64_t count=0;
    for(;;){
        ssize_t n=read(out->fd,block,sizeof block);
        if(n<0 && errno==EINTR)continue;
        if(n<0)refuse("bundle_readback",68);
        if(!n)break;
        count+=(uint64_t)n;if(count>out->bytes)refuse("bundle_readback",68);
        hash_update(&hash,block,(size_t)n);
    }
    hash_finish(&hash,observed);
    int fd=open_absolute(path,READ_FLAGS);
    if(fd<0 || fstat(fd,&named) || fstat(out->fd,&after) || !S_ISREG(before.st_mode) ||
       before.st_nlink!=1 || count!=out->bytes || (uint64_t)before.st_size!=count ||
       !same_stat(&before,&after) || !same_stat(&before,&named) || memcmp(expected,observed,32))refuse("bundle_readback",68);
    close(fd);close(out->fd);
}
static void execute_link(char **argv) {
    char global[ABS_PATH_BYTES+64],local[ABS_PATH_BYTES+64],library[ABS_PATH_BYTES+64],temporary[ABS_PATH_BYTES+64];
    char zig_directory[ABS_PATH_BYTES+1];strcpy(zig_directory,argv[1]);*strrchr(zig_directory,'/')=0;
    if(snprintf(global,sizeof global,"ZIG_GLOBAL_CACHE_DIR=%s",argv[2])<0 ||
       snprintf(local,sizeof local,"ZIG_LOCAL_CACHE_DIR=%s",argv[3])<0 ||
       snprintf(library,sizeof library,"ZIG_LIB_DIR=%s/lib",zig_directory)<0 ||
       snprintf(temporary,sizeof temporary,"TMPDIR=%s",argv[3])<0)refuse("argument_path",64);
    char *environment[]={"LANG=C","LC_ALL=C","TZ=UTC","SOURCE_DATE_EPOCH=0","HOME=/nonexistent",
                         global,local,library,temporary,NULL};
    char *command[]={argv[1],"cc","-target","x86_64-linux-musl","-static","-o",argv[4],
                     argv[6],argv[7],argv[8],"-lm","-lpthread","-lc",NULL};
    pid_t child=fork();if(child<0)refuse("fork",66);
    if(!child){execve(argv[1],command,environment);_exit(127);}
    int status;pid_t waited;
    do{waited=waitpid(child,&status,0);}while(waited<0 && errno==EINTR);
    if(waited!=child || !WIFEXITED(status) || WEXITSTATUS(status))refuse("seed_link",66);
}
int main(int argc,char **argv) {
    if(argc!=9)refuse("arguments",64);
    for(int i=1;i<argc;i++)absolute_path(argv[i]);
    for(int i=1;i<argc;i++)for(int j=i+1;j<argc;j++)if(overlap(argv[i],argv[j]) || overlap(argv[j],argv[i]))refuse("argument_overlap",64);
    struct stat input;
    for(int i=1;i<argc;i++)if(i==1 || i>=6){
        int fd=open_absolute(argv[i],READ_FLAGS);
        if(fd<0 || fstat(fd,&input) || !S_ISREG(input.st_mode) || !input.st_size ||
           (i==1 && !(input.st_mode&0111)))refuse("input",65);
        close(fd);
    }
    int seed=reserve_output(argv[4]);
    if(fchmod(seed,0700) || fsync(seed))refuse("seed_reserve",65);
    close(seed);
    struct output out={.fd=reserve_output(argv[5]),.bytes=0};hash_init(&out.digest);
    int roots[2]={create_cache(argv[2]),create_cache(argv[3])};
    const char *paths[2]={argv[2],argv[3]};
    execute_link(argv);
    int image=open_absolute(argv[4],READ_FLAGS);struct stat image_info;
    if(image<0 || fstat(image,&image_info) || !S_ISREG(image_info.st_mode) || image_info.st_nlink!=1 ||
       image_info.st_size<=0 || (uint64_t)image_info.st_size>MAX_SEED_BYTES || !(image_info.st_mode&0111) || fsync(image))refuse("seed_output",66);
    close(image);
    struct stat root_info[2];
    for(unsigned i=0;i<2;i++)if(fstat(roots[i],&root_info[i]) ||
       root_info[i].st_mode!=(S_IFDIR|0700))refuse("cache_root",67);
    struct inventory before=scan_caches(roots,paths,root_info);
    export_inventory(&out,&before,roots,root_info);
    struct inventory after=scan_caches(roots,paths,root_info);
    compare_inventories(&before,&after);verify_bundle(&out,argv[5]);
    free(before.rows);free(after.rows);close(roots[0]);close(roots[1]);
    return 0;
}
