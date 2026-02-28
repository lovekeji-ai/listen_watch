#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#include <sys/stat.h>

int main(void) {
    /* 定位可执行文件所在目录 */
    char exe[1024];
    uint32_t sz = sizeof(exe);
    if (_NSGetExecutablePath(exe, &sz) != 0) {
        fprintf(stderr, "launcher: _NSGetExecutablePath failed\n");
        return 1;
    }

    /* MacOS/ → Contents/ → listen_watch.app/ → PROJECT_DIR/ */
    char resolved[1024];
    if (!realpath(exe, resolved)) {
        perror("realpath");
        return 1;
    }
    char *dir = dirname(resolved);       /* .../MacOS           */
    char project[1024];
    snprintf(project, sizeof(project), "%s/../../..", dir);

    char project_real[1024];
    if (!realpath(project, project_real)) {
        perror("realpath project");
        return 1;
    }

    /* 确保 ~/.listen_watch 存在 */
    char *home = getenv("HOME");
    char logdir[1024];
    snprintf(logdir, sizeof(logdir), "%s/.listen_watch", home);
    mkdir(logdir, 0755);

    /* stderr → error.log */
    char errlog[1024];
    snprintf(errlog, sizeof(errlog), "%s/error.log", logdir);
    freopen(errlog, "a", stderr);

    /* chdir 到项目目录 (.env 从这里加载) */
    chdir(project_real);

    /* 构造 python 和 main.py 路径 */
    char python[1024], mainpy[1024];
    snprintf(python, sizeof(python), "%s/.venv/bin/python3", project_real);
    snprintf(mainpy, sizeof(mainpy), "%s/main.py", project_real);

    /* exec python3 main.py */
    execl(python, "python3", mainpy, (char *)NULL);
    perror("execl failed");
    return 1;
}
