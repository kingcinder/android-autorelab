from __future__ import annotations

from pathlib import Path

from arelab.runner import ToolRunner


DEMO_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int check_admin_token(const char *role, int pin_ok) {
    int is_admin = strcmp(role, "admin") == 0;
    if (!pin_ok) {
        puts("pin failed");
    }
    return is_admin || pin_ok;
}

static int vulnerable_copy(const char *input) {
    char buffer[16];
    strcpy(buffer, input);
    return (int)buffer[0];
}

static int multiply_count(const char *count_str) {
    int count = atoi(count_str);
    int bytes = count * 4096;
    char *heap = (char *)malloc(bytes);
    if (!heap) {
        return -1;
    }
    memset(heap, 0, bytes);
    free(heap);
    return bytes;
}

int main(int argc, char **argv) {
    const char *role = argc > 1 ? argv[1] : "guest";
    const char *payload = argc > 2 ? argv[2] : "hello";
    const char *count = argc > 3 ? argv[3] : "2";
    int auth = check_admin_token(role, argc > 4);
    printf("auth=%d copy=%d bytes=%d\n", auth, vulnerable_copy(payload), multiply_count(count));
    return 0;
}
""".strip()


def build_demo_inputs(repo_root: Path, work_dir: Path, runner: ToolRunner, tools: dict[str, str | None]) -> Path:
    sample_dir = work_dir / "demo-inputs"
    sample_dir.mkdir(parents=True, exist_ok=True)
    source_path = sample_dir / "swap_demo.c"
    source_path.write_text(DEMO_C + "\n", encoding="utf-8")
    gcc = tools.get("gcc")
    if not gcc:
        raise RuntimeError("gcc is required for the proof run")
    runner.run(
        "build-demo-x86_64",
        [
            gcc,
            "-g",
            "-O0",
            "-fno-stack-protector",
            "-no-pie",
            "-o",
            str(sample_dir / "swap-demo-x86_64"),
            str(source_path),
        ],
    )
    if tools.get("aarch64_gcc"):
        runner.run(
            "build-demo-aarch64",
            [
                tools["aarch64_gcc"] or "",
                "-g",
                "-O0",
                "-fno-stack-protector",
                "-o",
                str(sample_dir / "swap-demo-aarch64"),
                str(source_path),
            ],
            allow_failure=True,
        )
    return sample_dir
