"""make의 ARGS를 환경변수로 받아 유니코드 인수 배열로 uv에 전달한다."""

import os
import shlex
import subprocess
import sys


def split_arguments(value: str) -> list[str]:
    if not value.strip():
        return []
    if os.name != "nt":
        return shlex.split(value)

    # Windows의 경로 역슬래시와 큰따옴표 규칙을 그대로 사용한다.
    # https://learn.microsoft.com/windows/win32/api/shellapi/nf-shellapi-commandlinetoargvw
    import ctypes
    from ctypes import wintypes

    parse = ctypes.WinDLL("shell32", use_last_error=True).CommandLineToArgvW
    parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    count = ctypes.c_int()
    arguments = parse("make-args " + value, ctypes.byref(count))
    if not arguments:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [arguments[i] for i in range(1, count.value)]
    finally:
        free(ctypes.cast(arguments, ctypes.c_void_p))


def main(argv: list[str] | None = None) -> int:
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        print("실행할 명령이 필요하다", file=sys.stderr)
        return 2
    try:
        extra = split_arguments(os.environ.get("ARGS", ""))
        return subprocess.call(["uv", "run", "--no-sync", *command, *extra])
    except (OSError, ValueError) as exc:
        print(f"make 명령 실행 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
